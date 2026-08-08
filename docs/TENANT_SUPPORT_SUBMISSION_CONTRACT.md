# Tenant Support Submission Contract

## Status and current boundary

The backend submission endpoint and bounded frontend form are implemented. The
main shared testing Supabase has migration 030 applied and verified with
fake/team data, and local browser/API E2E verification passed with fake data.
This is not staging verification or production readiness.

The current tenant `support.html` page provides authenticated help topics,
account context, navigation, and the bounded submission form. There is no
tenant ticket inbox, ticket history, or customer-facing support workflow.
Existing Support Cases are internal platform-admin cases created from the
Platform-admin Support Workspace.

## Submission endpoint contract

The first tenant endpoint is:

```text
POST /api/support/requests
```

It must use `token_required` and the refreshed database-backed authentication
context. The server derives both `company_id` and requester `user_id` from the
authenticated user. The browser must never be trusted to provide ownership or
platform identity.

The request must reject or ignore:

- `company_id` and arbitrary requester `user_id`;
- platform-admin IDs or mapping IDs;
- status, assignment, priority escalation, or closure state;
- audit metadata or actor fields;
- secrets, tokens, cookies, payment references, gateway data, or provider
  payloads.

## Allowed first-version fields

- `category`: a server-owned allowlist such as technical, account, chatbot,
  integration, billing question, AI credits, or other;
- `title`: 1–160 characters;
- `redacted_description`: 1–2,000 characters.

Tenant-selected priority is excluded from the first version. The server sets
priority to `normal`.

## Schema and actor decision

The existing `platform_support_cases` schema cannot safely support tenant-created
cases as-is:

- `created_by_platform_admin_user_id` is mandatory;
- `platform_support_case_events.actor_platform_admin_user_id` is mandatory;
- no tenant requester field exists;
- the current audit model expects a platform-admin actor.

The approved tenant requester/source actor model is implemented by Migration 030
and the atomic creation RPC. Tenant submissions must never be attributed to a
fake or shared platform-admin mapping. Migration 030 is applied and verified
only in the main shared testing Supabase with fake/team data. It does not modify
`platform_support_cases`, `platform_support_case_events`, or
`platform_admin_users`. This is not staging verification or production
readiness.

## Audit and atomicity contract

Tenant submission audit must represent the tenant actor safely. It must not
write fabricated platform-admin audit rows. Safe metadata may include company
ID, requester ID where approved, category, source, outcome, case ID, and
timestamp.

Never record titles, descriptions, secrets, tokens, cookies, payment
references, provider payloads, full request bodies, or customer conversation
content. Case creation, the initial append-only event, and audit evidence must
commit atomically through an approved transaction/RPC or equivalent mechanism.
Audit failure must prevent a false success response.

## Abuse, privacy, and retention controls

Before staging or production use, approve and test:

- per-user and per-company rate limits;
- a daily submission cap;
- a duplicate-suppression window;
- strict field lengths and category validation;
- sensitive-text rejection/redaction policy;
- retention and deletion rules;
- no attachments in the first version.

## Frontend contract

`support.html` now includes a bounded first-version form with a category
selector, title or subject, and redacted description. It submits only
`category`, `title`, and `redacted_description`, warns users not to include
secrets or payment details, and provides loading, success, validation,
rate-limit, and error states.

The first version must not add an inbox, messaging thread, billing action,
impersonation, export, chart, attachment, or email integration.

## Explicit exclusions

- no tenant ticket inbox or history yet;
- no two-way messaging, live chat, or customer contact workflow;
- no email notifications;
- no attachments;
- no billing or remediation actions;
- no platform-admin impersonation;
- no exports or charts.

## Approval gates

Further rollout requires approval of:

- schema migration and tenant actor model;
- tenant audit metadata and atomicity design;
- abuse limits and duplicate policy;
- retention and privacy rules;
- focused backend, migration, and frontend tests;
- a shared-testing or staging verification plan.

The current internal platform-admin Support Cases workflow remains separate.
Further staging or production rollout remains gated. Migration 030 and local browser/API E2E
verification are recorded only for the main shared testing Supabase with
fake/team data. Tenant inbox/history, messaging, email, attachments, billing
actions, impersonation, exports, and charts remain excluded. No staging or
production claim is made.

## Main shared-testing verification evidence

The verified fake-data run recorded one request, one `created` event, and one
audit event. The request source was `tenant`, with status `new`, priority
`normal`, and category `technical`. The event used actor type `tenant` with a
tenant user actor and no platform-admin actor. The audit action was
`tenant_support.request.create` with outcome `success` and source `tenant`.
Safe audit output exposed no title, description, or full request body.
