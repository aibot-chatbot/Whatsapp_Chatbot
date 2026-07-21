# Company 20 and Chatbot 26 Orphan-Retirement Runbook

## Status

**Prepared for review only; retirement is not approved or executed.** The
production Supabase project is `parjsxypengvubziwwjp`. Company 20 and chatbot 26
remain present. No SQL in this runbook is executable write SQL, and no change to
production data, company IDs, tenant roles, billing, platform-admin records, or
audit history is authorized.

Company 20 is a candidate orphan, not yet a deletable orphan. Chatbot 26 is an
owned row and its remaining dependencies have not been fully resolved because
the final catalog-generated production counts have not been run.

## Non-negotiable separation

This retirement must use a different change ticket, approval, window,
transaction, evidence bundle, and rollback plan from the company 1 identity
correction. Failure or cancellation here must have no effect on company 1,
user 3, chatbots 29/38, subscriptions, payment history, AI credit, usage, or
platform administration.

Do not use company retirement as a shortcut for correcting company 1 labels.
Do not reassign chatbot 26 or any child row to company 1.

## Entry criteria

All criteria are mandatory:

- production project reference and backend target independently verified;
- `docs/company_1_20_final_read_only_inspection.sql` hash recorded and run;
- all direct `company_id=20` counts are zero except the company and chatbot 26;
- all direct `chatbot_id=26` counts are zero;
- all single-column FK-generated counts are zero;
- every composite FK and recursive descendant is manually resolved and zero;
- every conversation, campaign, channel, knowledge-file, and other generated
  indirect-path count is zero;
- no storage object, webhook registration, scheduled job, provider-side
  integration, DNS/routing entry, analytics export, or support workflow refers
  to chatbot 26 or company 20;
- chatbot 26's status and deletion preconditions are documented;
- no user belongs to company 20;
- no platform-admin mapping resolves through company 20 users;
- explicit absence evidence is retained for every other audit, incident,
  billing, payment, credit, usage, storage, and external-control-plane
  reference before any retirement decision;
- legal, finance, security, database, product, and operations owners approve;
  and
- backup/PITR and isolated restoration evidence is current.

Any nonzero or unknown result is a stop condition. Do not classify a missing
query, inaccessible control plane, absent permission, or SQL error as zero.

## Read-only dry run

1. Record UTC time, operator, approver, second verifier, project reference,
   backend and database release identity, script hash, and ticket.
2. Run catalog discovery and retain every table/column/FK result.
3. Run the known chatbot 26 and company 20 count blocks.
4. Run every generated SELECT-only count statement unchanged.
5. Resolve every composite FK and recursive path with an explicit count-only
   query reviewed by the database owner.
6. Compare the resulting table set against repository access, Supabase storage,
   scheduled jobs, webhook/provider configuration, observability, and support
   tooling.
7. Repeat the complete counts immediately before the future write transaction.
   Any drift cancels the change.

The signed dry-run manifest must list every discovered table even when its
count is zero. A summary saying "no dependencies" without the manifest is not
sufficient evidence.

## Foreign-key-derived retirement order

The exact order must be generated from the retained live FK graph, not copied
blindly from repository migrations. The database owner must topologically sort
the live dependency graph from deepest child to parent and attach it to the
change ticket.

For the currently known ownership paths, the review order is:

1. leaf records through campaigns, conversations, channels, and files;
2. direct chatbot child records;
3. chatbot 26;
4. any direct company 20 child records; and
5. company 20 last.

The known leaf-before-parent relationships include:

- broadcast logs before broadcast campaigns;
- messages and conversation-scoped children before conversations;
- processed Telegram/Wasender records before their channel rows;
- knowledge chunks and graph edges before graph nodes/files where live FKs
  require it;
- CRM leads and agent actions before their conversation/chatbot parents;
- bot configuration and webhook-deduplication rows before chatbot 26; and
- every chatbot child before chatbot 26, then chatbot 26 before company 20.

However, the approved zero-dependency policy means none of those child rows
should require deletion. If all gates pass, the future retirement transaction's
effective target order should be only chatbot 26 first and company 20 last.
Discovery of any child row blocks retirement and requires a new preservation or
remediation design; it does not expand this ticket into a cascading cleanup.

Do not rely on `ON DELETE CASCADE`. Record every live FK's update/delete action
and prove that deleting the two approved rows cannot reach company 1 or an
unlisted table. Use strict identity and ownership predicates, row locks, and
expected row counts in the separately reviewed future write script.

## Existing chatbot-deletion RPC is not pre-approved

The repository's permanent-chatbot deletion RPC covers several known tables and
preserves AI usage, but repository code is not evidence that it covers every
live table. It also intentionally deletes child records, while this runbook
requires zero child records before retirement.

Do not invoke the RPC unless a separate review proves its live definition,
ownership, grants, search path, table coverage, preservation behavior, and
transactional result exactly match this retirement policy. The default plan is
to prepare a narrowly scoped, separately reviewed transaction only after zero
dependencies are proven.

## Backup and rollback requirements

Before the future write window:

- verify backup/PITR status and perform an isolated restoration rehearsal;
- export safe, complete row snapshots for company 20 and chatbot 26 into the
  restricted evidence store, with checksums and schema definitions;
- record identity/sequence behavior needed to restore the exact IDs;
- capture live FK, constraint, index, trigger, RLS, policy, owner, and grant
  definitions affecting both tables;
- prepare and peer-review an exact restoration script, but do not execute it;
- record external storage/integration absence evidence; and
- name the rollback owner and maximum decision time.

The future write operation must be one explicit transaction and must abort on
any ownership mismatch, changed timestamp/version, unexpected child count,
unexpected row count, trigger error, or FK error. Do not retry with constraints
disabled and do not widen predicates during the window.

Before commit, verify within the same transaction that:

- exactly the approved chatbot and company rows are absent from the transaction
  view;
- no company 1/user 3/chatbot 29/chatbot 38 row changed;
- company 1 billing, balances, ledger, usage, and operational row counts match
  the preflight snapshot; and
- platform-admin mappings and audit-event counts match the preflight snapshot.

If validation fails before commit, roll back the transaction. If a post-commit
problem is discovered, stop all related maintenance, preserve logs/evidence,
open an incident, and restore only through the approved restoration procedure
or PITR decision. Never recreate approximate rows manually.

## Post-retirement verification

After a future approved commit:

- rerun the focused identity queries and require company 20/chatbot 26 absent;
- rerun every generated dependency count and require zero;
- confirm company 1, user 3, and chatbots 29/38 are unchanged;
- verify company 1 tenant login, chatbot access, Pro subscription, order
  history, AI-credit balance, ledger, usage, and platform-admin read behavior;
- confirm no alert, FK violation, webhook retry, background-job failure, or
  storage/control-plane orphan appears;
- monitor for attempted access to IDs 20/26 for the approved observation period;
  and
- retain redacted outputs, transaction result, approvals, checksums, timestamps,
  and verifier sign-off.

Do not reuse retired numeric IDs. Identity sequences must remain ahead of all
existing and retired IDs.

## No-cascade-surprise checklist

- [ ] Live direct FKs to companies and chatbots retained.
- [ ] Recursive FK descendants retained and topologically ordered.
- [ ] Composite FKs resolved manually.
- [ ] Non-FK ownership columns counted.
- [ ] Conversation/campaign/channel/file indirect paths counted.
- [ ] Triggers and functions inspected for hidden writes.
- [ ] RLS, owner, grants, and executor behavior reviewed.
- [ ] Storage and external control-plane references checked.
- [ ] Company 1 invariants captured before and verified after.
- [ ] Platform-admin mapping/audit invariants captured before and verified after.
- [ ] Future write and restore scripts independently reviewed.

## Approvals still required

- business owner confirms company 20/chatbot 26 have no legitimate purpose;
- database owner accepts the complete dependency manifest and exact order;
- security owner confirms no audit/incident evidence would be destroyed;
- finance owner confirms no billing/payment/credit history is attached;
- legal/privacy owner approves retention and deletion;
- operations owner confirms storage, integration, job, and monitoring cleanup;
- product owner confirms no customer tenant is affected;
- change approver authorizes the separate production window; and
- operator, second verifier, and rollback owner are named.
