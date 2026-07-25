# CRM Leads and Agent Actions Hardening: Phase 1-5 Review Package

## Status and purpose

Migration `027` was applied and verified successfully in staging on 2026-07-25.
Production has not been updated. The migration established historical ownership
backfill, referential integrity, compatible value constraints, targeted indexes,
and a service-role-only access boundary for:

- `public.agent_actions`
- `public.crm_leads`

The expanded AI Signal lifecycle, signal-to-lead links, message ID population,
and application behavior changes remain deferred.

The exact historical orphans were approved and removed by migration `028` in
staging before migration `027` ran. Production cleanup and hardening remain
separately controlled changes.

## Staging verification result

- Migration `028` deleted exactly 36 orphan Agent Actions and 2 orphan CRM leads.
- Cleanup verification returned zero orphan failures and no valid-row change.
- Migration `027` then applied successfully with both PL/pgSQL `END;`
  terminators present.
- All four chatbot/conversation foreign keys and all seven value checks are
  validated.
- Both proposed indexes exist and are valid.
- RLS is enabled but not forced; both tables have zero policies.
- `anon` and `authenticated` have no target table or sequence privileges.
- `service_role` has only `SELECT`, `INSERT`, and `UPDATE` on both tables plus
  required sequence `USAGE`.
- Ownership and relationship mismatch counts are zero.
- The permanent chatbot deletion RPC remains `SECURITY DEFINER`, executable by
  `service_role`, and unavailable to browser roles and PUBLIC.
- Direct company foreign keys remain deferred under Option C.

## Confirmed live baseline

The July 2026 live inspection found:

- `agent_actions`: 112 rows, including 109 null `company_id` values, 36 missing
  chatbot references, 36 missing conversation references, and 112 null
  `message_id` values. RLS is disabled and the table has no foreign keys,
  value checks, policies, or uniqueness constraints.
- `crm_leads`: 3 rows, including 2 missing chatbot references and 2 missing
  conversation references. RLS is enabled without policies and the table has no
  foreign keys, value checks, or uniqueness constraints.
- Existing populated ownership agrees with surviving chatbot ownership.
- Historical `general_question` intent and `escalate` action values must remain
  compatible.
- No duplicate open CRM lead key was found. Duplicate-looking Agent Actions
  groups are not proven duplicates and are not changed by this package.

These counts are evidence for review, not a replacement for re-running the
preflight immediately before any approved staging attempt.

The final safety review also found that company deletion semantics are not
defined end to end:

- `docs/PLATFORM_ADMIN_PHASE_1_SCHEMA.md:38` records
  `users.company_id -> companies.id ON DELETE CASCADE`.
- The available repository migrations do not establish or document the live
  `chatbots.company_id -> companies.id` delete action.
- `app/database/company_repository.py:13-73` supports create, read, and update,
  but no company deletion.
- `app/database/platform_company_repository.py:33-72` and
  `app/routes/platform_admin_routes.py:54-79` expose read-only platform company
  access, not tenant deletion.
- `tests/test_platform_admin_frontend.py:300-319` asserts that platform-admin
  screens expose no mutation route or Delete Company control.
- No application company-delete route, service, repository operation, or
  company-deletion RPC was found.

## Package files

Run and review the files in this order:

1. `scripts/crm_agent_actions_hardening_preflight.sql`
2. A separately approved backup/export and orphan disposition process
3. `data/027_harden_crm_agent_actions.sql` (verified in staging)
4. `scripts/crm_agent_actions_hardening_verification.sql`
5. `scripts/crm_agent_actions_hardening_rollback.sql` only if an approved
   rollback is required

The earlier broad inspection remains available in
`scripts/platform_crm_agent_actions_schema_inspection.sql`.

## Mandatory approval gates

### Gate 1: backup and evidence

Before any migration attempt:

- Take a restorable database backup using the approved Supabase process.
- Export the two target tables with access limited to authorized operators.
- Run the preflight and preserve every result set and error without editing.
- Record current constraints, policies, table grants, sequence grants, RLS
  flags, and permanent-deletion RPC execution grants.

No sensitive customer content should be copied into the review. The supplied
preflight uses aggregates and identifiers only.

### Gate 2: historical orphan disposition

The candidate migration does not delete, archive, or null orphan references.
The team must separately review and explicitly approve a disposition for:

- Agent Actions whose chatbot no longer exists
- Agent Actions whose non-null conversation no longer exists
- CRM leads whose chatbot no longer exists
- CRM leads whose non-null conversation no longer exists

Options such as export-and-delete or clearing an optional conversation reference
are intentionally outside this package. The migration fails before DDL and
grant changes while any such orphan remains.

### Gate 3: integrity preconditions

Immediately before any future environment application, all of the following
must be zero:

- Null `agent_actions.company_id` after authoritative chatbot-derived backfill
- Missing company or chatbot references
- Missing non-null conversation references
- Company ownership mismatches
- Conversation/chatbot mismatches
- Values outside the proposed checks
- Duplicate open CRM leads for a non-null `(chatbot_id, conversation_id)` key

The permanent chatbot deletion RPC must exist with the inspected signature, and
`service_role` must retain `EXECUTE`.

### Gate 4: access-model approval

Approve the service-role-only model before applying grant changes:

- `anon`, `authenticated`, and `PUBLIC` receive no direct target-table
  privileges or related sequence privileges.
- `service_role` receives `SELECT`, `INSERT`, and `UPDATE` on both tables.
- Direct `DELETE` is not granted because the current permanent chatbot deletion
  path is a `SECURITY DEFINER` RPC that explicitly deletes both dependent tables
  before the chatbot.
- The application still has to enforce tenant and chatbot ownership. Supabase
  `service_role` may have `BYPASSRLS`, and the migration does not force RLS.

The proposed target matrix is:

| Role | `agent_actions` | `crm_leads` | Related sequences |
| --- | --- | --- | --- |
| `postgres` | owner privileges | owner privileges | owner privileges |
| `service_role` | `SELECT`, `INSERT`, `UPDATE` | `SELECT`, `INSERT`, `UPDATE` | `USAGE`, `SELECT` |
| `authenticated` | none | none | none |
| `anon` | none | none | none |
| `PUBLIC` | none | none | none |

Before approval, verify there are no external operational jobs that directly
delete CRM leads or Agent Actions as `service_role`.

This focused migration does not change database-wide default privileges for
future objects. Those should be audited and proposed separately so unrelated
tables and functions are not affected.

### Gate 5: company-deletion policy

Migration `027` adopts **Option C** and defers direct company foreign keys. A
future migration must not choose company `RESTRICT` or `CASCADE` until all of
the following are reviewed and approved:

- The live `chatbots.company_id` foreign-key actions
- Every company-deletion or account-deletion RPC and its execution grants
- Whether tenant deletion should retain, export, or remove CRM and signal data
- Interaction with existing cascading and audit-preserving foreign keys
- A tested, explicit account/tenant deletion workflow

The expanded preflight reports database evidence for this gate. Until the
decision is made, migration `027` retains authoritative ownership, company
existence and mismatch preconditions, and `company_id NOT NULL`, without
introducing either destructive cascade or deletion-blocking semantics.

## Proposed migration behavior

### Authoritative ownership backfill

Only null `agent_actions.company_id` values with a surviving chatbot are
backfilled, using `chatbots.company_id`. Conversation data, request data,
channel payloads, JWTs, and client-provided company context are not used.

The update is inside the migration transaction. If a precondition fails, the
transaction aborts and the backfill is rolled back with the rest of the
migration.

### Foreign keys and nullability

The proposal uses `NOT VALID` chatbot and conversation foreign keys and
validates them explicitly:

| Child column | Parent | Delete action | Nullability |
| --- | --- | --- | --- |
| `agent_actions.chatbot_id` | `chatbots.id` | `CASCADE` | remains required |
| `agent_actions.conversation_id` | `conversations.id` | `SET NULL` | remains nullable |
| `crm_leads.chatbot_id` | `chatbots.id` | `CASCADE` | remains required |
| `crm_leads.conversation_id` | `conversations.id` | `SET NULL` | remains nullable |

All use `ON UPDATE NO ACTION`. `agent_actions.company_id` becomes required after
the authoritative backfill and gates pass; `crm_leads.company_id` remains
required. Neither receives a direct company foreign key in migration `027`.
No `message_id` foreign key is proposed because the live column is empty and
its intended parent/key semantics have not been confirmed.

This is Option C. It is safer than `RESTRICT` or `CASCADE` for the current
architecture because the repository contains no tenant deletion workflow and
does not record the live chatbot/company delete action. The migration therefore
does not silently make operational records block company deletion or silently
make company deletion destroy those records.

The preflight reports whether `chatbots(id, company_id)` has a supporting unique
parent key. The migration does not add a speculative parent uniqueness
constraint or composite foreign key. Consequently, simple foreign keys do not
alone prove that a child row's company and chatbot pair agree; application
ownership checks and the migration mismatch gate remain essential. Composite
ownership enforcement is a future separately reviewed change.

The chatbot `CASCADE` behavior is compatible with the current permanent deletion
RPC, which explicitly deletes `crm_leads` and `agent_actions` before deleting the
chatbot. The explicit order remains the active path; the foreign key cascade is
a database integrity fallback.

### DELETE privilege evidence

The application scan found no direct `.delete()` operation for either target
table:

- `app/database/agent_action_repository.py:8-135` uses `SELECT`, `INSERT`, and
  `UPDATE`.
- `app/database/crm_lead_repository.py:85-374` uses `SELECT`, `INSERT`, and
  `UPDATE`.
- `app/database/bot_repository.py:153-166` calls the approved permanent-delete
  RPC rather than deleting target tables directly.
- `data/022_permanently_delete_archived_chatbot_rpc.sql:93-106` explicitly
  deletes CRM leads and Agent Actions before the chatbot.
- `data/022_permanently_delete_archived_chatbot_rpc.sql:130-136` revokes PUBLIC
  execution and grants RPC execution to `service_role`.

Accordingly, direct `service_role DELETE` is not required by the current
repositories. This conclusion must be rechecked if an external job or
out-of-repository integration is discovered.

### Compatible value checks

The proposal validates:

- Agent Action status: `detected`, `resolved`
- Agent Action intent: `greeting`, `general_question`, `lead_interest`,
  `handoff_request`, `complaint`, `knowledge_gap`, `unknown`
- Agent Action action type: `answer`, `ask_follow_up`, `create_lead`,
  `request_handoff`, `escalate`, `log_knowledge_gap`, `none`
- Agent Action confidence: null or between 0 and 1
- CRM status: `new`, `in_progress`, `contacted`, `closed`
- CRM priority: `low`, `medium`, `high`
- CRM lead type: `follow_up`, `staff_attention`, `negative_feedback`

Each check is added `NOT VALID` and then explicitly validated. The historical
`general_question` and `escalate` values are preserved.

### Indexes and duplicate prevention

The proposal adds:

- `(chatbot_id, status, created_at DESC)` on `agent_actions`, matching the
  pending-action equality/filter/order pattern more closely than the existing
  `(chatbot_id, created_at)` index.
- A partial unique index on CRM `(chatbot_id, conversation_id)` for non-null
  conversations with status `new`, `in_progress`, or `contacted`.

The CRM index allows closed historical leads and leaves conversation-less leads
outside the uniqueness rule. The existing read-then-write application flow can
still race; after migration approval, a later application phase should catch
unique violations or use an atomic idempotent write. This package does not
change that runtime behavior.

No Agent Action uniqueness is added without a stable message-level idempotency
key.

## Recorded staging procedure

The following sequence completed successfully in staging. Retain it as the
required pattern for any separately approved environment:

1. Schedule a maintenance window. The migration uses transactional DDL
   and creates a non-concurrent unique index, so it can take table locks.
2. Restore or refresh staging with a representative, protected data snapshot.
3. Run the preflight. Stop if any expected-zero result is nonzero.
4. Review the reported chatbot/company FK action, company deletion functions,
   function grants, and company triggers. Keep direct company FKs deferred.
5. Confirm the backup/export and orphan-disposition approvals in the change
   record.
6. Review function and grant dependencies, including external jobs.
7. Run migration `027` once.
8. Run the verification SQL and preserve every result set and error.
9. Run backend smoke tests for signal recording, insights, lead creation/update,
   and permanent archived-chatbot deletion.
10. Observe logs and query performance before any production proposal.

Do not retry a failed migration by editing or deleting live rows ad hoc. Return
to the preflight and approval process.

## Rollback

The rollback removes only the constraints and indexes introduced by migration
`027`, drops the new Agent Action `company_id` nullability requirement, restores
the inspected RLS flags, and can restore the confirmed live table-grant
baseline.

Limitations:

- It does not clear authoritative `company_id` backfills. Full data reversal
  requires restoring the pre-migration backup.
- It does not guess prior sequence privileges. Restore those only from the
  captured preflight evidence under explicit approval.
- Restoring the old browser grants recreates known security weaknesses. Use that
  path only for an approved emergency rollback.
- A transaction failure before commit requires no rollback; PostgreSQL rolls
  back the candidate migration atomically.

## Deferred decisions

This package intentionally does not decide or implement:

- Production cleanup or archival handling for the historical orphan scope
- Direct `agent_actions.company_id` or `crm_leads.company_id` foreign keys and
  the associated tenant-deletion policy
- Composite chatbot/company foreign keys
- `message_id` population or referential integrity
- Expanded signal statuses or review/audit timestamps
- Signal dispositions or a direct signal-to-lead link
- Agent Action deduplication
- Atomic CRM lead upsert/idempotency handling
- Forced RLS or authenticated tenant policies
- Production execution timing

Each remains subject to separate approval before future implementation or
production rollout.
