# Tenant Identity Drift Remediation: Companies 1 and 20

## Status and safety boundary

**Production investigation complete enough to select a canonical tenant;
remediation is not approved or executed.** The target Supabase project is
`parjsxypengvubziwwjp`, and the current backend uses that project. Treat every
future database action as production work.

No write SQL was executed during this investigation. This package does not
authorize an update, reassignment, merge, deletion, migration, deployment, or
platform-admin change. Company 20 and chatbot 26 remain present. Company IDs,
user 3, billing, credits, usage, operational records, and platform-admin records
must remain unchanged until separately approved change tickets are executed.

## Canonical-company conclusion

Company 1 is the canonical operational tenant. This conclusion is based on a
consistent ownership chain rather than company display fields:

- user 3 logs in as `iomaths123@gmail.com` and belongs to company 1;
- that normalized email occurs once in `users`;
- company 1 owns chatbots 29 and 38;
- company 1 owns the active Pro subscription and subscription-order history;
- company 1 owns the AI-credit balance, ledger transactions, AI usage, and
  operational data;
- tenant authorization and billing scope use company 1; and
- `abc@gmail.com` is not an application user.

Company 1's current `ABC Property` / `abc@gmail.com` fields are therefore an
identity-label problem, not evidence that operational records belong elsewhere.
Do not move company 1 data to company 20 to make labels align.

Company 20 is a candidate orphan. It has no known user, subscription, order,
credit balance, credit transaction, AI usage, conversation, message, knowledge,
channel, bot configuration, CRM, agent-action, broadcast, or invitation record.
It owns chatbot 26, so it is not yet proven empty and cannot be retired until
all direct and indirect chatbot references are shown to be zero.

## Required final read-only evidence

Use
`docs/company_1_20_final_read_only_inspection.sql` in the production project's
SQL Editor. It is a two-pass inspection:

1. Verify the project reference in the Supabase UI and run catalog discovery.
2. Retain every `company_id`, `chatbot_id`, direct-FK, and recursive-FK result.
3. Run all known count-only checks.
4. Review and run every generated SELECT-only count query.
5. Write safe count queries for any composite FK or recursive path not covered
   by the generators.
6. Check storage and integration control planes for chatbot 26 without reading
   object content or credentials.

Chatbot 26 has **unresolved dependencies** until all generated checks have been
run. Repository inspection cannot substitute for live catalog output, and no
SQL was run while preparing this package.

The final evidence bundle must contain the project reference, UTC execution
time, operator and verifier, release/backend commit, unmodified script hash,
catalog output, every generated statement, every count result, and a signed
zero-dependency conclusion or a stop decision.

## Root-cause analysis

### User and company contact email drift

`PUT /api/user` accepts an email and sends only `users.email` to `update_user`.
It does not load or update the company. `company_repository.py` has company
creation but no authorized company-profile update method. Consequently,
`companies.contact_email` remains the registration-time snapshot while the
login email can change.

The application does not consistently treat the two fields as the same
identity:

- authentication and checkout use `users.email`;
- tenant ownership uses `company_id`;
- handoff notifications use active company users; and
- platform administration displays `companies.contact_email`.

There is no application-level requirement that the fields match. Registration
initializes them to the same value, which creates an implicit expectation the
later update path does not preserve.

Repository evidence:

- `app/routes/user_routes.py:update_current_user` builds a user-only email
  payload;
- `app/database/user_repository.py:update_user` writes that payload only to
  `users`;
- `app/database/company_repository.py` exposes company creation but no company
  identity update; and
- billing checkout resolves the customer email from the authenticated user.

### Partial registration can orphan a company

Email/OTP completion currently performs separate operations:

1. create the company;
2. create the user;
3. mark the user verified;
4. initialize the default subscription; and
5. remove the pending registration.

The sequence is not one database transaction. OTP completion does not recheck
the normalized email immediately before creating the company. A duplicate,
repeated, or concurrent verification can therefore create a company and then
fail during user creation, leaving the company behind. Company creation also
does not prevent reuse of an existing user or company contact email.

This is a strong hypothesis for company 20, not proof of its historical cause.
Creation timestamps, safe pending-registration identity evidence, deployment
history, and operator records should be correlated before the incident record
is finalized.

The relevant flow is in `app/routes/auth_routes.py:verify_otp`, which calls
`create_company` before `create_user`. The initial registration check blocks an
existing user only when the first returned row is verified, while
`app/database/user_repository.py:get_user_by_email` performs an unordered
single-row lookup. `app/decorators/auth_decorator.py` refreshes user status but
continues to populate tenant company context from the JWT claim.

## Preferred remediation: Option A

Keep company 1 and every existing ownership relationship unchanged.

### Approved scope to define before execution

The business owner must approve exact replacement values for these company 1
fields individually:

- `company_name`;
- `business_type`, if necessary;
- `contact_email`;
- `contact_phone`, if necessary; and
- the explicit `updated_at` behavior.

No other column belongs in the correction. User 3's email and company ID must
not change. The change must not touch chatbots, subscriptions, orders, balances,
credit transactions, AI usage, conversations, knowledge, integrations, audit
history, or platform-admin records.

Chatbot-facing brand text may live independently in chatbot configuration or
profiles. Any branding correction must use a separate reviewed scope listing
the exact chatbot IDs and safe fields. Do not couple branding edits to the
company-row correction, and do not alter AI/provider settings, prompts,
knowledge, channels, or chatbot ownership.

### Production execution package still required

Before writing data, prepare a separate change ticket containing:

- exact before/after values and affected-row expectation of one company row;
- a transaction-scoped write script with a strict `id = 1` predicate and
  before-value predicates to prevent overwriting concurrent changes;
- a returned safe projection for second-person verification;
- pre-change backup/PITR confirmation;
- rollback values captured from the immediately preceding read;
- tenant login, company-profile, chatbot-access, billing, and platform-read
  smoke checks; and
- monitoring and abort criteria.

No write script or migration is included in this package.

## Why records must not move to company 20

Reassigning operational data would cross multiple security and accounting
boundaries. It would affect or risk:

- JWT and repository tenant scope;
- users and team membership;
- chatbots 29 and 38 and every indirect chatbot record;
- active subscription state and payment-order reconciliation;
- AI-credit balance and immutable ledger/usage history;
- channels, webhook deduplication, conversations, messages, CRM, and knowledge;
- billing notifications and receipts; and
- audit chronology and incident evidence.

It would also create rollback ambiguity across tables with different FK,
cascade, uniqueness, and append-only behavior. Moving company 1 records is
rejected unless future evidence disproves the canonical conclusion and a
separate migration design is approved.

## Preventive code changes

Implement these in a later application/database phase, not in the remediation
data-change ticket:

1. Replace multi-call registration completion with one transactional database
   operation for company, initial owner, verification state, and subscription
   initialization or a precisely documented compensating model.
2. Normalize emails consistently and enforce a case-insensitive unique
   `users.email` constraint after a duplicate-data preflight.
3. Make OTP completion idempotent using a stable registration identifier and a
   database uniqueness/claim boundary.
4. Recheck normalized user email inside the same transaction immediately before
   tenant creation.
5. Guarantee that user-creation failure rolls back company creation.
6. Make normalized-email lookup deterministic and fail closed if historical
   duplicates are detected; do not use an unordered `LIMIT 1` as identity
   resolution.
7. Refresh tenant `company_id` from the current user row on authenticated
   requests, with a compatibility rollout and tests, rather than continuing to
   authorize solely from a stale JWT company claim.

### Company contact-email policy requiring approval

Choose exactly one model:

**A. Independent company contact field — recommended.** A company contact is a
tenant-level operational address and is not necessarily a login. Add an
owner/admin-authorized company-profile API and UI, validate and audit changes,
and label the fields distinctly. User profile updates must not silently alter
the company contact.

**B. Synchronize with an approved owner email.** Define which owner is
authoritative, how multiple owners are handled, what happens on ownership
transfer/deactivation, and how changes are verified. Update both identities in
one transaction and audit both. Do not synchronize from an arbitrary admin or
member profile update.

Do not impose uniqueness on `companies.contact_email` without a business-policy
decision; shared finance/support inboxes may legitimately serve more than one
company.

## Required tests

### Registration and identity

- user-creation failure leaves no company or subscription row;
- normalized/case-variant duplicate user email is rejected by the database;
- concurrent OTP completion creates exactly one company and one owner;
- repeated OTP completion returns the existing completed result without writes;
- an email conflict detected immediately before creation aborts everything;
- subscription initialization failure follows the approved atomic or
  compensating behavior without creating an unusable orphan tenant;
- deterministic email lookup fails closed on duplicate historical rows.

### Profile and company contact policy

- user email update follows the approved independent/synchronized policy;
- unauthorized roles cannot change company identity;
- company contact validation, audit, concurrency, and rollback behavior;
- changing a member/admin email never silently changes company contact;
- ownership transfer behavior if synchronized-owner policy is selected.

### Tenant authorization and regression

- stale JWT `company_id` cannot retain access after user reassignment;
- current database user status and company membership control every request;
- company 1 retains Pro billing, balance, ledger, usage, and chatbot 29/38 access
  after an identity-only correction;
- no company 20 or chatbot 26 record is read or changed by company 1 correction;
- tenant admin and platform-admin authorization semantics remain unchanged.

### Orphan detection

- discovers every live public `company_id` and `chatbot_id` column;
- discovers direct and recursive FKs even with nonstandard column names;
- counts conversation, campaign, channel, file, and other indirect paths;
- treats an unknown/composite path as blocking, never as zero;
- excludes sensitive columns and refuses broad row projections;
- detects storage/control-plane objects that lack database rows.

## Rollback strategy

For the future company 1 identity correction, rollback means restoring only the
captured company identity fields under a second approved transaction. Company
IDs and operational ownership never move, so billing and audit rollback is not
required. If any smoke check shows tenant scope, billing, chatbot, or
platform-admin impact, stop, restore the captured fields, revoke the change
window, and investigate before retrying.

Company 20/chatbot 26 retirement has a different rollback model and must not
share a transaction or ticket with Option A. See
`docs/company_20_orphan_retirement_runbook.md`.

## Approval gates

- production project identity and backend configuration independently verified;
- business owner approves canonical company 1 and exact identity values;
- security and database owners accept the complete read-only lineage evidence;
- product owner selects the company contact-email policy;
- database owner approves future transactional registration design and email
  uniqueness preflight;
- backup/PITR and restoration evidence accepted;
- operator, approver, second verifier, rollback owner, and change window named;
- Option A write script separately reviewed; and
- company 20 retirement remains a separate no-go until its runbook gates pass.
