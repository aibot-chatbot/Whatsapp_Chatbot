# CRM Leads and Agent Actions Orphan Cleanup Approval

## Status

The exact deletion scope below was approved by the user on 2026-07-25.
Staging-first migration `028` was applied successfully in staging on 2026-07-25:
exactly 36 Agent Actions and 2 CRM leads were deleted, verification returned
zero orphan failures, and valid-row counts were unchanged. Production has not
been updated.

Migration `027` was applied and verified separately in staging after migration
`028`. They must remain separate SQL migrations and separate production
deployment steps, but their reviewed repository artifacts may be committed
together atomically.

The repository does not record backup/export identifiers, checksum, archive
location, or restoration owner. Do not infer those values from staging success;
they remain mandatory evidence before any production proposal.

## Confirmed evidence

- Thirty-six Agent Actions have missing chatbot and conversation parents.
- Thirty-five have null ownership that cannot be inferred; one has populated
  `company_id`.
- CRM lead ID 1 is indirectly associated with 29 orphan Agent Actions.
- CRM lead ID 2 is indirectly associated with 3 orphan Agent Actions.
- Four orphan Agent Actions have no matching CRM lead.
- No incoming foreign keys, candidate audit/lifecycle/link columns, views,
  materialized views, or user-defined triggers currently block a separately
  approved cleanup.
- The only routine reference is
  `public.permanently_delete_archived_chatbot()`.

The associations are inferred from equal non-null `chatbot_id` and
`conversation_id`; no direct signal-to-lead foreign key exists.

## Approved exact identifier manifest

- `CRM-ORPHAN-BATCH-001`
  - CRM lead: `1`
  - Agent Actions: `1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 22, 23, 24, 25, 26, 27,
    28, 29, 30, 31, 32, 33, 34, 71, 72, 73, 74, 102, 103`
- `CRM-ORPHAN-BATCH-002`
  - CRM lead: `2`
  - Agent Actions: `11, 12, 21`
- `CRM-ORPHAN-BATCH-003`
  - CRM lead: none
  - Agent Actions: `13, 35, 36, 75`

Approval applies only to these 2 CRM lead IDs and 36 Agent Action IDs. A count
match cannot authorize a substituted or additional identifier.

## Candidate evidence

Run `scripts/crm_agent_actions_orphan_cleanup_candidates.sql` only after
authorization to collect read-only evidence. Preserve every result and error
without modification.

The script derives action membership from current live relationships. It
hard-codes only the two reviewed CRM lead anchors and independently verifies
counts, exclusivity, parent state, completeness, and ownership totals.

Required evidence outputs:

1. Identifier-only candidate rows
2. Exact CRM lead and Agent Action identifier manifests
3. Expected-count gates
4. Cross-batch exclusivity gate
5. Current-parent validity gate
6. Completeness gate
7. Ownership-count evidence

No batch may advance if any expected-count boolean is false, overlap count is
nonzero, valid parent count is nonzero, omitted count is nonzero, or ownership
counts differ from confirmed evidence.

## Proposed batches

### CRM-ORPHAN-BATCH-001

- CRM lead anchor: ID 1
- Expected CRM leads: 1
- Expected linked Agent Actions: 29
- Link evidence: same non-null `chatbot_id` and `conversation_id`
- Proposed disposition: export to an approved restricted archive, verify
  checksum and restore procedure, then delete from active tables only through a
  separately approved cleanup migration
- Future deletion order: exact approved Agent Action identifiers first, then
  CRM lead ID 1

### CRM-ORPHAN-BATCH-002

- CRM lead anchor: ID 2
- Expected CRM leads: 1
- Expected linked Agent Actions: 3
- Link evidence: same non-null `chatbot_id` and `conversation_id`
- Proposed disposition: export to an approved restricted archive, verify
  checksum and restore procedure, then delete from active tables only through a
  separately approved cleanup migration
- Future deletion order: exact approved Agent Action identifiers first, then
  CRM lead ID 2

### CRM-ORPHAN-BATCH-003

- CRM lead anchor: none
- Expected CRM leads: 0
- Expected standalone Agent Actions: 4
- Membership evidence: missing chatbot and conversation parents, with no
  matching orphan CRM lead on the same non-null relationship key
- Proposed disposition: export to an approved restricted archive, verify
  checksum and restore procedure, then delete from active tables only through a
  separately approved cleanup migration
- Future deletion order: exact approved Agent Action identifiers only

Agent Actions precede their linked CRM lead to preserve a deterministic
child-before-anchor sequence. The current inspection found no direct foreign
key, but this order remains safer if dependencies change between review and an
approved cleanup rehearsal.

## Formal approval record

The exact deletion scope is approved. Operational evidence and role-specific
approval fields remain unassigned until recorded. The exact identifier manifest
must remain attached to each record.

| Field | CRM-ORPHAN-BATCH-001 | CRM-ORPHAN-BATCH-002 | CRM-ORPHAN-BATCH-003 |
| --- | --- | --- | --- |
| Expected CRM lead count | 1 | 1 | 0 |
| Expected Agent Action count | 29 | 3 | 4 |
| Evidence query/result location | Unassigned | Unassigned | Unassigned |
| Proposed disposition | Restricted export, then separate approved cleanup | Restricted export, then separate approved cleanup | Restricted export, then separate approved cleanup |
| Business owner | Unassigned | Unassigned | Unassigned |
| Technical approver | Unassigned | Unassigned | Unassigned |
| Data-retention approver | Unassigned | Unassigned | Unassigned |
| Backup identifier | Unassigned | Unassigned | Unassigned |
| Export manifest identifier | Unassigned | Unassigned | Unassigned |
| SHA-256 checksum | Unassigned | Unassigned | Unassigned |
| Authorized archive location | Unassigned | Unassigned | Unassigned |
| Retention period | Unassigned | Unassigned | Unassigned |
| Restoration owner | Unassigned | Unassigned | Unassigned |
| Staging rehearsal status | Applied and verified 2026-07-25 | Applied and verified 2026-07-25 | Applied and verified 2026-07-25 |
| Approval status | Staging deletion complete; production not approved | Staging deletion complete; production not approved | Staging deletion complete; production not approved |
| User scope-approval date | 2026-07-25 | 2026-07-25 | 2026-07-25 |
| Business approval timestamp | Unassigned | Unassigned | Unassigned |
| Technical approval timestamp | Unassigned | Unassigned | Unassigned |
| Data-retention approval timestamp | Unassigned | Unassigned | Unassigned |

The archive location must provide encryption in transit and at rest,
least-privilege access, MFA, access logging, and approved retention controls.
The manifest must preserve exact record type and row identifiers, source
environment, UTC export time, and SHA-256 checksum.

## Required production execution sequence

Production deletion remains unapproved and must not begin until steps 1-5 have
recorded evidence:

1. Create and verify a restorable backup.
2. Export the exact approved identifiers and complete records to the authorized
   restricted archive.
3. Generate and independently verify the checksum manifest.
4. Rehearse restoration and record the result.
5. Obtain business-owner, technical, and data-retention approvals.
6. Review the preserved staging evidence for cleanup migration `028`.
7. Preserve staging post-cleanup verification proving only approved identifiers
   changed.
8. Rerun the migration `027` preflight.
9. Apply migrations `028` and `027` as separate production deployment steps,
   with verification between them, only after every applicable gate passes.

Cleanup migration `028` and hardening migration `027` must retain separate
approval records, deployment steps, and database transactions. Their reviewed
application code, SQL, tests, scripts, and documentation may be committed
together as one atomic Git commit.

## Requirements enforced by cleanup migration 028

Migration `028` must:

- Use the exact approved CRM lead and Agent Action identifiers.
- Fail closed if any expected batch count differs.
- Fail closed if any row has regained a valid chatbot or conversation.
- Fail closed if any linked relationship differs from the approved evidence.
- Fail closed if any row appears in multiple batches or any orphan is omitted.
- Use one transaction.
- Delete Agent Actions before their linked CRM lead in batches 1 and 2.
- Delete no unrelated row.
- Preserve the documented limitation that deleted data can be restored only
  from the approved backup/archive.
- Never use broad predicates such as only `chatbot_id IS NULL`.
- Never infer eligibility from aggregate row counts alone.
- Verify exact identifiers again immediately before mutation.

Migration `028` contains explicit expected-count assertions before mutation and
post-mutation assertions before commit. It is verified in staging and remains a
separate production change from migration `027`.

## Approval statement

Deletion of only the exact identifiers above was approved and completed in
staging. Backup/export identifiers, checksum, archive location, retention
period, and restoration owner remain unrecorded in the repository. No production
cleanup or hardening is authorized or recorded as complete.
