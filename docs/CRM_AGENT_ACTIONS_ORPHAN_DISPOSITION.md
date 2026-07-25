# CRM Leads and Agent Actions Orphan Disposition Review

## Status and purpose

This began as a **review-only, non-destructive** package. The user approved
deletion of the exact 38-record manifest documented in
`docs/CRM_AGENT_ACTIONS_ORPHAN_CLEANUP_APPROVAL.md` on 2026-07-25. Migration
`028` subsequently deleted those records successfully in staging; verification
found zero remaining orphans and no valid-row changes. Production is unchanged.

The purpose is to give business, technical, and data-retention approvers
identifier-only evidence for every known orphan before any separate cleanup
migration is designed.

Confirmed starting evidence:

- 36 Agent Actions reference missing chatbots.
- 36 Agent Actions reference missing conversations.
- 2 CRM leads reference missing chatbots.
- 2 CRM leads reference missing conversations.
- Surviving populated ownership values are consistent.
- Migration `027` fails closed while missing chatbot or non-null conversation
  references remain.
- Company deletion semantics remain unresolved, and direct company foreign keys
  remain deferred under Option C.

These counts can overlap. The review SQL must determine the exact combination
for each identifier rather than assuming all missing-parent counts describe the
same rows.

## Running the review

The only SQL file in this package is
`scripts/crm_agent_actions_orphan_review.sql`. It contains only `SELECT` and
`WITH ... SELECT` statements.

When authorized to collect evidence:

1. Confirm the intended Supabase project in the SQL Editor.
2. Run the complete review SQL without editing projections.
3. Preserve every result section and error exactly.
4. Store the results in the approved restricted evidence location.
5. Populate the decision ledger below from the preserved results.
6. Do not create or execute cleanup SQL until every required approval is
   recorded.

The SQL was not run against Supabase while this package was prepared.

## Classification model

Classifications intentionally overlap. A-D describe parent existence; E
describes chatbot/conversation disagreement; Agent Action F-G describe ownership
inference. One row may therefore appear in more than one result category.

### Agent Actions

| Code | Classification | Initial disposition category |
| --- | --- | --- |
| AA-A | Chatbot exists and conversation exists | Retain unchanged candidate |
| AA-B | Chatbot exists but non-null conversation is missing | Retain after clearing optional conversation candidate |
| AA-C | Chatbot missing but conversation exists | Manual relationship review |
| AA-D | Chatbot and non-null conversation both missing | Export/archive or delete pending approval |
| AA-E | Conversation belongs to a different chatbot | Manual relationship review |
| AA-F | Null company ownership can be authoritatively backfilled from chatbot | Retain after ownership backfill candidate |
| AA-G | Null company ownership cannot be safely inferred | Export/archive or delete pending approval |

An absent optional `conversation_id` is reported separately and is not labelled
as an orphan.

### CRM Leads

| Code | Classification | Initial disposition category |
| --- | --- | --- |
| CRM-A | Chatbot exists and conversation exists | Retain unchanged candidate |
| CRM-B | Chatbot exists but non-null conversation is missing | Retain after clearing optional conversation candidate |
| CRM-C | Chatbot missing but conversation exists | Manual relationship review |
| CRM-D | Chatbot and non-null conversation both missing | Export/archive or delete pending approval |
| CRM-E | Conversation belongs to a different chatbot | Manual relationship review |
| CRM-F | Company ownership disagrees with surviving chatbot ownership | Manual relationship review |

The category is a review aid, not authorization. A row is not approved for a
disposition merely because the SQL suggests a category.

## Sensitive-data boundary

Identifier review output is restricted to:

- Row ID
- `company_id`
- `chatbot_id`
- `conversation_id`
- Status
- Intent or lead type
- Creation timestamp
- Classification
- Recommended disposition category

Dependency sections additionally return database object metadata and linked
record IDs/counts. The SQL excludes customer content, message content, payloads,
notes, reasons, phone numbers, customer names, usernames, emails, credentials,
and channel identifiers.

Do not expand the projections or attach sensitive source rows to the ledger.

## Dependency review

Before assigning any destructive disposition, preserve the results for:

- Incoming foreign keys referencing either target table
- Candidate audit, history, lifecycle, event, link, or mapping columns
- Views and materialized views referencing the tables
- Functions and procedures referencing the tables
- Triggers on the target tables
- Orphan Agent Actions linked indirectly to CRM leads by matching non-null
  `chatbot_id` and `conversation_id`
- Orphan CRM leads linked indirectly to Agent Actions by the same key

The indirect match is evidence only. It does not assert a direct foreign-key
relationship.

If the catalog returns an incoming foreign key or a candidate non-FK dependency
column, disposition is blocked until a schema-specific, separately reviewed
read-only query confirms whether the orphan identifiers are actually present in
that dependent object. This package deliberately avoids dynamic SQL against
arbitrary tables and does not treat a similarly named column as proof of a
relationship.

Application-visible paths also exist independently of database views:

- `app/database/agent_action_repository.py:39-135` reads and resolves Agent
  Actions.
- `app/routes/analytics_routes.py:238-264` exposes authorized AI Signal results.
- `app/database/crm_lead_repository.py:85-374` reads and updates CRM leads.
- `app/routes/crm_routes.py:20-226` exposes chatbot-scoped CRM operations.
- `data/022_permanently_delete_archived_chatbot_rpc.sql:93-106` is the only
  approved repository-backed path currently found to delete both target tables.

Human reviewers must consider whether a retained orphan would still be
application-accessible after its chatbot has disappeared.

## Proposed disposition categories

### Retain unchanged

Use only when all required relationships and ownership remain valid. Confirm
that the row does not also appear in a mismatch classification.

### Retain after ownership backfill

Limited to Agent Actions with a surviving chatbot and authoritative
`chatbots.company_id`. The backfill must use that chatbot value only. This
document does not generate or approve the update.

### Retain after clearing optional conversation reference

Consider only when:

- The chatbot exists.
- The non-null conversation reference is missing.
- The column remains optional.
- The record retains operational or historical business value.
- Business, technical, and data-retention reviewers explicitly approve it.

No statement that clears `conversation_id` is included.

### Export and archive outside active tables

Use for possible historical, audit, support, or legal value without a valid
operational parent. Do not create an archive table without separate approval.

An approved export plan must specify:

- An organization-approved evidence vault or object store
- Encryption in transit and at rest
- Least-privilege access, MFA, and access logging
- A SHA-256 checksum manifest
- UTC export timestamp and source environment identifier
- Approved retention period and destruction date
- Restore owner, restore steps, and a restore verification procedure

The source repository, issue trackers, chat messages, and personal storage are
not authorized archive locations.

### Export and delete

Use only for records confirmed irreparable and no longer operationally,
contractually, legally, or historically required. Deletion requires:

- A restorable pre-cleanup backup
- A reviewed, immutable identifier list
- Business-owner approval
- Data-retention approval
- Technical approval
- A separate cleanup migration
- Staging rehearsal
- Preserved post-cleanup verification

No deletion statement is included or approved by this package.

## Decision ledger

These classification-level entries began **Not approved** and remain historical
review evidence. Exact cleanup batches 001-003 are approved separately in the
cleanup approval record. Replace “Populate from review SQL” only from preserved
result sets; do not combine classifications merely because their counts match.

| Classification | Row count | Proposed disposition | Business owner | Technical approver | Data-retention approver | Approval status | Evidence location | Cleanup batch identifier |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AA-A | Populate from review SQL | Retain unchanged candidate | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| AA-B | Populate from review SQL | Clear optional conversation candidate | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| AA-C | Populate from review SQL | Manual relationship review | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| AA-D | Populate from review SQL | Export/archive or delete pending review | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| AA-E | Populate from review SQL | Manual relationship review | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| AA-F | Populate from review SQL | Ownership backfill candidate | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| AA-G | Populate from review SQL | Export/archive or delete pending review | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| CRM-A | Populate from review SQL | Retain unchanged candidate | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| CRM-B | Populate from review SQL | Clear optional conversation candidate | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| CRM-C | Populate from review SQL | Manual relationship review | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| CRM-D | Populate from review SQL | Export/archive or delete pending review | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| CRM-E | Populate from review SQL | Manual relationship review | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |
| CRM-F | Populate from review SQL | Manual relationship review | Unassigned | Unassigned | Unassigned | Not approved | Unassigned | Unassigned |

Record every approved cleanup batch separately. A cleanup batch identifier must
refer to a fixed identifier manifest and must never be reused.

## Migration 027 readiness

Migration `027` may proceed to staging application only after:

- Missing chatbot references equal zero.
- Missing non-null conversation references equal zero.
- Ownership mismatches equal zero.
- Every destructive action has a restorable backup and recorded approvals.
- Cleanup verification and evidence have been preserved.
- The migration preflight passes in staging.
- The known company-deletion uncertainty remains isolated by the approved
  Option C deferral of direct company foreign keys.

Those conditions passed in staging and migration `027` was applied successfully
there. Production remains unchanged and requires its own approval and preflight.

## Approval record

The exact identifier scope for cleanup batches 001-003 is approved by the user;
see `docs/CRM_AGENT_ACTIONS_ORPHAN_CLEANUP_APPROVAL.md`. The classification
ledger above remains historical review evidence rather than the executable
manifest.

The repository does not record the backup, export manifest, checksum, archive
location, retention period, or restoration owner. Staging execution and
verification are complete; production execution remains pending. Migrations
`028` and `027` remain separate production changes.
