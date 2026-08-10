# Platform Admin Audit Policy

## Status and authority

**Production policy candidate; formal security, privacy, legal, and data-owner
approval remains required.** This policy matches the implemented read-only
platform-admin endpoint set, including the application-only operations overview,
company-user, chatbot, subscription-history, AI-credit transaction-history,
billing-order history, support-case operations, tenant-visible support replies,
audit-log viewer extensions, and the Phase 4 platform-admin user-management
actions, plus the Phase 5 bounded tenant/company lifecycle actions. It does
not authorize production deployment, retention deletion, staging readiness, or
production mapping activation.

The platform-admin service is fail closed: a successful or not-found platform
response must not be returned unless its audit event is inserted successfully.
Audit failure returns a sanitized 503 and withholds fetched tenant data.

## Scope and principles

- The audit stream covers the separate platform-admin console only. Tenant
  `users.role` values do not grant platform access or identify an audit actor.
- `platform_admin_user_id` identifies the active allowlist mapping row.
- Events are append-only. Application code must never UPDATE or DELETE them.
- Metadata is structured context, not a request/response capture mechanism.
- Collect the minimum information needed for accountability, investigation,
  access review, and request-to-audit reconciliation.
- Never use audit metadata to store customer content, secrets, or full personal
  records.

## Approved actions, resources, and metadata schemas

No action or resource type outside this table is approved. Support Cases Phase
1 and Platform-admin Support Case Operations Phase 2 are verified only in the
main shared-testing Supabase with fake/team data. Platform-admin Tenant
Communication Phase 3 and Migration 033 are verified only in the main
shared-testing Supabase with fake/team data. This is not staging verification
and does not establish production readiness.
Platform-admin User Management Phase 4 and Migration 034 are applied and
structurally verified only in the approved main shared-testing Supabase with
fake/team data. Company 29 is registered as the protected internal company for
main shared-testing only. This is not staging verification and does not
establish production readiness. Migration 035 is applied and verified only in
the approved main shared-testing Supabase with fake/team data. It corrected only
the Phase 4 RPC audit endpoint metadata, preserved RPC ownership/security/
EXECUTE posture, did not create mappings, did not create Phase 4 mutation audit
events merely by application, and did not alter existing audit rows.
Platform-admin Tenant and Company Administration Phase 5 and Migration 036 are
applied and verified only in the approved main shared-testing Supabase with
fake/team data. This verified company 23 suspend/restore lifecycle audit rows
and company 29 protected-company rejection, but it is not staging verification
and does not establish production readiness.

| Action | Resource type | Resource ID | Outcomes | Required metadata | Optional metadata | Endpoint |
|---|---|---|---|---|---|---|
| `platform_admin.identity.read` | `platform_admin` | Platform-admin mapping ID as positive integer text | `success` | `outcome`, `endpoint`, `http_method` | None | `/api/platform-admin/me` |
| `platform_admin.company.list` | `company` | `NULL` | `success` | `outcome`, `endpoint`, `http_method`, `limit`, `offset`, `sort_by`, `sort_order`, `search_applied`, `status_filter`, `returned_count` | None | `/api/platform-admin/companies` |
| `platform_admin.company.read` | `company` | Requested company ID as positive integer text | `success`, `not_found` | `outcome`, `endpoint`, `http_method` | None | `/api/platform-admin/companies/<company_id>` |
| `platform_admin.company.suspend` | `company` | Target company ID as positive integer text | `success` | `outcome`, `endpoint`, `http_method`, `company_id`, `old_status`, `new_status` | None | `POST /api/platform-admin/companies/<company_id>/suspend` |
| `platform_admin.company.restore` | `company` | Target company ID as positive integer text | `success` | `outcome`, `endpoint`, `http_method`, `company_id`, `old_status`, `new_status` | None | `POST /api/platform-admin/companies/<company_id>/restore` |
| `platform_admin.company.subscription.read` | `company_subscription` | Requested company ID as positive integer text | `success`, `not_found` | `outcome`, `endpoint`, `http_method` | None | `/api/platform-admin/companies/<company_id>/subscription` |
| `platform_admin.company.subscription_history.read` | `company_subscription_history` | Requested company ID as positive integer text | `success`, `not_found` | `outcome`, `endpoint`, `http_method`; plus `limit`, `offset`, `status_filter`, and `returned_count` when `outcome = success` | None | `/api/platform-admin/companies/<company_id>/subscription-history` |
| `platform_admin.company.ai_credit_usage.read` | `company_ai_credit_usage` | Requested company ID as positive integer text | `success`, `not_found` | `outcome`, `endpoint`, `http_method`; plus `period_start` and `period_end` when `outcome = success` | None for `success`; no period fields for `not_found` | `/api/platform-admin/companies/<company_id>/ai-credit-usage` |
| `platform_admin.company.ai_credit_transactions.read` | `company_ai_credit_transactions` | Requested company ID as positive integer text | `success`, `not_found` | `outcome`, `endpoint`, `http_method`; plus `limit`, `offset`, `transaction_type_filter`, and `returned_count` when `outcome = success` | None | `/api/platform-admin/companies/<company_id>/ai-credit-transactions` |
| `platform_admin.company.billing_orders.read` | `company_billing_orders` | Requested company ID as positive integer text | `success`, `not_found` | `outcome`, `endpoint`, `http_method`; plus `limit`, `offset`, `status_filter_applied`, `created_after_filter_applied`, `created_before_filter_applied`, and `returned_count` when `outcome = success` | None | `/api/platform-admin/companies/<company_id>/billing-orders` |
| `platform_admin.company.users.read` | `company_users` | Requested company ID as positive integer text | `success`, `not_found` | `outcome`, `endpoint`, `http_method`; plus `limit`, `offset`, `sort_by`, `sort_order`, `search_applied`, and `returned_count` when `outcome = success` | None | `/api/platform-admin/companies/<company_id>/users` |
| `platform_admin.company.chatbots.read` | `company_chatbots` | Requested company ID as positive integer text | `success`, `not_found` | `outcome`, `endpoint`, `http_method`; plus `limit`, `offset`, `sort_by`, `sort_order`, `search_applied`, `state_filter`, and `returned_count` when `outcome = success` | None | `/api/platform-admin/companies/<company_id>/chatbots` |
| `platform_admin.operations.overview.read` | `platform_operations_overview` | `NULL` | `success` | `outcome`, `endpoint`, `http_method`, `attention_company_count`, `generated_at` | None | `/api/platform-admin/overview` |
| `platform_admin.audit_events.list` | `platform_admin_audit_events` | `NULL` | `success` | `outcome`, `endpoint`, `http_method`, `limit`, `offset`, `action_filter_applied`, `resource_type_filter_applied`, `actor_user_id_filter_applied`, `resource_id_filter_applied`, `created_after_filter_applied`, `created_before_filter_applied`, `returned_count` | None | `/api/platform-admin/audit-events` |
| `platform_admin.support_case.list` | `platform_support_cases` | `NULL` | `success` | `outcome`, `endpoint`, `http_method`, `limit`, `offset`, filter-applied flags, `returned_count` | None | `/api/platform-admin/support-cases` |
| `platform_admin.support_case.read` | `platform_support_cases` | Case ID | `success`, `not_found` | `outcome`, `endpoint`, `http_method` | None | `/api/platform-admin/support-cases/<case_id>` |
| `platform_admin.support_case.create` | `platform_support_cases` | Case ID | `success` | `outcome`, `endpoint`, `http_method`, `company_id` | `status`, `priority` | `POST /api/platform-admin/support-cases` |
| `platform_admin.support_case.note.create` | `platform_support_case_events` | Case ID | `success` | `outcome`, `endpoint`, `http_method` | None | `POST /api/platform-admin/support-cases/<case_id>/notes` |
| `platform_admin.support_case.assignee.list` | `platform_admin_users` | `NULL` | `success` | `outcome`, `endpoint`, `http_method`, `returned_count` | None | `GET /api/platform-admin/support-case-assignees` |
| `platform_admin.support_case.assign` | `platform_support_cases` | Case ID | `success` | `outcome`, `endpoint`, `http_method`, `old_assigned_platform_admin_user_id`, `new_assigned_platform_admin_user_id` | None | `PATCH /api/platform-admin/support-cases/<case_id>/assignment` |
| `platform_admin.support_case.unassign` | `platform_support_cases` | Case ID | `success` | `outcome`, `endpoint`, `http_method`, `old_assigned_platform_admin_user_id`, `new_assigned_platform_admin_user_id` | None | `PATCH /api/platform-admin/support-cases/<case_id>/assignment` |
| `platform_admin.support_case.status.update` | `platform_support_cases` | Case ID | `success` | `outcome`, `endpoint`, `http_method`, `old_status`, `new_status` | None | `PATCH /api/platform-admin/support-cases/<case_id>/status` |
| `platform_admin.support_case.priority.update` | `platform_support_cases` | Case ID | `success` | `outcome`, `endpoint`, `http_method`, `old_priority`, `new_priority` | None | `PATCH /api/platform-admin/support-cases/<case_id>/priority` |
| `platform_admin.support_case.reply.list` | `platform_support_cases` | Case ID | `success`, `not_found` | `outcome`, `endpoint`, `http_method`, `returned_count` | `request_id`, `company_id` | `GET /api/platform-admin/support-cases/<case_id>/replies` |
| `platform_admin.support_case.reply.create` | `tenant_support_replies` | Reply ID | `success` | `outcome`, `endpoint`, `http_method`, `case_id`, `request_id`, `company_id`, `reply_id`, `notification_channel`, `delivery_status` | None | `POST /api/platform-admin/support-cases/<case_id>/replies` |
| `platform_admin.user.list` | `platform_admin_users` | `NULL` | `success` | `outcome`, `endpoint`, `http_method`, `returned_count` | None | `GET /api/platform-admin/platform-admin-users` |
| `platform_admin.user.read` | `platform_admin_users` | Target mapping ID | `success`, `not_found` | `outcome`, `endpoint`, `http_method`, `target_platform_admin_user_id` | `target_user_id`, `old_is_active`, `new_is_active` | `GET /api/platform-admin/platform-admin-users/<platform_admin_user_id>` |
| `platform_admin.user.create` | `platform_admin_users` | Newly created mapping ID | `success` | `outcome`, `endpoint`, `http_method`, `target_platform_admin_user_id`, `target_user_id`, `old_is_active`, `new_is_active` | None | `POST /api/platform-admin/platform-admin-users` |
| `platform_admin.user.activate` | `platform_admin_users` | Target mapping ID | `success` | `outcome`, `endpoint`, `http_method`, `target_platform_admin_user_id`, `target_user_id`, `old_is_active`, `new_is_active` | None | `PATCH /api/platform-admin/platform-admin-users/<platform_admin_user_id>/active` |
| `platform_admin.user.deactivate` | `platform_admin_users` | Target mapping ID | `success` | `outcome`, `endpoint`, `http_method`, `target_platform_admin_user_id`, `target_user_id`, `old_is_active`, `new_is_active` | None | `PATCH /api/platform-admin/platform-admin-users/<platform_admin_user_id>/active` |

### Operations-overview fields

| Field | Allowed value |
|---|---|
| `attention_company_count` | Integer from 0 through 10; booleans are rejected |
| `generated_at` | Valid timezone-aware ISO-8601 timestamp |

`resource_id`, when present, must be a non-blank string no longer than 255
characters and must contain only the canonical positive numeric ID for the implemented
resources—not a company name, email, URL, external payment ID, or composite
payload.

The repository validation boundary enforces this exact action/resource-type
matrix. An action paired with any other resource type is rejected even if both
values are independently recognized.

## Metadata schemas and allowlist

The complete top-level allowlist is:

```text
outcome
endpoint
http_method
limit
offset
sort_by
sort_order
search_applied
status_filter
state_filter
transaction_type_filter
status_filter_applied
returned_count
period_start
period_end
attention_company_count
generated_at
action_filter_applied
resource_type_filter_applied
actor_user_id_filter_applied
resource_id_filter_applied
created_after_filter_applied
created_before_filter_applied
company_filter_applied
priority_filter_applied
company_id
status
priority
old_status
new_status
old_priority
new_priority
old_assigned_platform_admin_user_id
new_assigned_platform_admin_user_id
case_id
request_id
reply_id
notification_channel
delivery_status
target_platform_admin_user_id
target_user_id
old_is_active
new_is_active
```

No additional key is permitted without a code change, security/privacy review,
tests, and a new policy approval.

Every action has an explicit schema. Unknown keys, missing required keys, wrong
types, and keys allowed for a different action are rejected. New audit actions
or metadata fields require an explicit schema and tests before use.

### Common fields for every action

| Field | Allowed value |
|---|---|
| `outcome` | `success` or `not_found` as applicable |
| `endpoint` | The fixed route template from the approved action table; never a full URL or query string |
| `http_method` | `GET` for approved investigation actions; `POST` or `PATCH` only for the explicitly approved bounded support-case, platform-admin user-management, and company lifecycle actions |

### Company-list fields

| Field | Allowed value |
|---|---|
| `limit` | Validated integer 1–100 |
| `offset` | Validated non-negative integer |
| `sort_by` | `created_at`, `company_name`, `status`, or `id` |
| `sort_order` | `asc` or `desc` |
| `search_applied` | Boolean only; never the search value |
| `status_filter` | `active`, `inactive`, or null |
| `returned_count` | Non-negative count for this page; must not exceed `limit` or 100 |

### AI-credit/usage fields

| Field | Allowed value |
|---|---|
| `period_start` | Required for successful AI-credit/usage reads; resolved ISO-8601 period boundary or null |
| `period_end` | Required for successful AI-credit/usage reads; resolved ISO-8601 period boundary or null |

`period_start` and `period_end` are not allowed on not-found AI-credit/usage
events because no tenant period has been read. Other action types use only
their common fields. Metadata must not duplicate actor IDs or resource IDs
already represented by table columns.

### Company subscription-history fields

These fields are present only when
`platform_admin.company.subscription_history.read` has `outcome = success`.
A missing company emits `outcome = not_found` with only the common fields.

The subscription-history endpoint lists persisted `company_subscriptions`
records. It is not an event-sourced audit timeline and must not be interpreted
as proof that every individual status transition is preserved as a separate
row.

| Field | Allowed value |
|---|---|
| `limit` | Validated integer 1-100 |
| `offset` | Validated non-negative integer |
| `status_filter` | `trialing`, `active`, `past_due`, `expired`, `cancelled`, or null |
| `returned_count` | Non-negative count for this page; must not exceed `limit` or 100 |

Metadata for this action must not include company names, plan names, plan
codes, subscription IDs, timestamps, payment or gateway identifiers, raw
errors, or response bodies.

### Company AI-credit transaction-history fields

These fields are present only when
`platform_admin.company.ai_credit_transactions.read` has `outcome = success`.
A missing company emits `outcome = not_found` with only the common fields.

The endpoint lists persisted `ai_credit_transactions` ledger records for one
company using safe operational fields only. It does not expose provider
economics, payment references, idempotency keys, AI-usage-log links,
subscription IDs, descriptions, or raw ledger row payloads.

| Field | Allowed value |
|---|---|
| `limit` | Validated integer 1-100 |
| `offset` | Validated non-negative integer |
| `transaction_type_filter` | `included_credit_grant`, `trial_credit_grant`, `usage_debit`, `topup_purchase`, `refund`, `manual_adjustment`, `expiry`, `reversal`, or null |
| `returned_count` | Non-negative count for this page; must not exceed `limit` or 100 |

Metadata for this action must not include transaction IDs, monetary values,
company names, subscription IDs, timestamps, provider details, payment
references, idempotency keys, descriptions, raw errors, or response bodies.

### Company billing-order history fields

These fields are present only when
`platform_admin.company.billing_orders.read` has `outcome = success`. A missing
company emits `outcome = not_found` with only the common fields.

The billing-order endpoint lists mutable operational
`company_subscription_orders` records for one company. It is not an
event-sourced payment lifecycle timeline and must not be interpreted as proof
that every checkout, callback, reconciliation, activation, or status transition
is preserved as a separate event row.

| Field | Allowed value |
|---|---|
| `limit` | Validated integer 1-100 |
| `offset` | Validated non-negative integer |
| `status_filter_applied` | Boolean only; never the raw status value |
| `created_after_filter_applied` | Boolean only; never the raw timestamp |
| `created_before_filter_applied` | Boolean only; never the raw timestamp |
| `returned_count` | Non-negative count for this page; must not exceed `limit` or 100 |

Metadata for this action must not include raw status values, raw timestamps,
order IDs, amount values, currency, company names, plan names, plan codes,
subscription IDs, payment or gateway identifiers, checkout URLs, idempotency
keys, reconciliation errors, raw errors, or response bodies.

### Company-user list fields

These fields are present only when `platform_admin.company.users.read` has
`outcome = success`. A missing company emits `outcome = not_found` with only
the common fields.

| Field | Allowed value |
|---|---|
| `limit` | Validated integer 1-100 |
| `offset` | Validated non-negative integer |
| `sort_by` | `created_at`, `email`, `full_name`, or `id` |
| `sort_order` | `asc` or `desc` |
| `search_applied` | Boolean only; never the search value |
| `returned_count` | Non-negative count for this page; must not exceed `limit` or 100 |

### Company-chatbot list fields

These fields are present only when `platform_admin.company.chatbots.read` has
`outcome = success`. A missing company emits `outcome = not_found` with only
the common fields.

| Field | Allowed value |
|---|---|
| `limit` | Validated integer 1-100 |
| `offset` | Validated non-negative integer |
| `sort_by` | `created_at`, `updated_at`, `bot_name`, or `id` |
| `sort_order` | `asc` or `desc` |
| `search_applied` | Boolean only; never the search value |
| `state_filter` | `current`, `archived`, or `all` |
| `returned_count` | Non-negative count for this page; must not exceed `limit` or 100 |

### Platform-admin audit-event viewer fields

These fields are present only when `platform_admin.audit_events.list` has
`outcome = success`.

The audit-log viewer lists safe summaries of persisted platform-admin audit
events. It returns the actor mapping ID only in Phase 1 and does not expose
actor email, actor full name, raw metadata JSON, tenant records, audit editing,
deletion, export, download, charts, retention controls, or platform-admin user
management.

| Field | Allowed value |
|---|---|
| `limit` | Validated integer 1-100 |
| `offset` | Validated non-negative integer |
| `action_filter_applied` | Boolean only; never the raw action value |
| `resource_type_filter_applied` | Boolean only; never the raw resource-type value |
| `actor_user_id_filter_applied` | Boolean only; never duplicate actor identity |
| `resource_id_filter_applied` | Boolean only; never the raw resource ID |
| `created_after_filter_applied` | Boolean only; never the raw timestamp |
| `created_before_filter_applied` | Boolean only; never the raw timestamp |
| `returned_count` | Non-negative count for this page; must not exceed `limit` or 100 |

Viewer responses must defensively return only the safe metadata subset from
stored events: `outcome`, `endpoint`, `http_method`, bounded list context,
operations-overview fields, AI-credit period fields, and the viewer filter
summary booleans. Unsupported or nested metadata is omitted from the response
even when it exists on a stored historical row.

### Support reply fields

`platform_admin.support_case.reply.create` metadata records only linkage and
delivery state: case ID, request ID, company ID, reply ID,
`notification_channel = in_app`, and `delivery_status = pending`. It must not
include the reply body, internal note body, email body, provider response,
tenant conversation content, or arbitrary client metadata.

`platform_admin.support_case.reply.list` records the fixed endpoint, method,
outcome, returned count, and optional request/company identifiers only. It must
not record reply text or notification failure details.

### Platform-admin user-management fields

Phase 4 user-management actions use `resource_type = platform_admin_users`.
Their resource ID semantics are:

- `platform_admin.user.list`: `resource_id` is `NULL`.
- `platform_admin.user.read`: `resource_id` is the target mapping ID.
- `platform_admin.user.create`: `resource_id` is the newly created mapping ID.
- `platform_admin.user.activate`: `resource_id` is the target mapping ID.
- `platform_admin.user.deactivate`: `resource_id` is the target mapping ID.

Approved metadata keys for these actions are `endpoint`, `http_method`,
`outcome`, `target_platform_admin_user_id`, `target_user_id`, `old_is_active`,
and `new_is_active`. Create records `old_is_active = null` and
`new_is_active = true`. Activation/deactivation records the previous and new
boolean state. Metadata must not include passwords, password hashes, tokens,
tenant roles, company names, user email/full name, raw request bodies, raw
exceptions, or arbitrary user data.

Migration 034 writes create, activate, and deactivate audit rows atomically from
the approved RPCs. The runtime list/read routes use these repository validation
schemas before returning successful directory or detail responses.

Migration 035 is the applied and verified corrective migration for the
already-applied Phase 4 RPCs. It preserves their business behavior and updates
only future mutation audit metadata to use
`/api/platform-admin/platform-admin-users` and
`/api/platform-admin/platform-admin-users/<platform_admin_user_id>/active`.
Existing audit rows were not rewritten, and the old shortened endpoint strings
are absent from the verified current main shared-testing RPC definitions.

## Prohibited data

Audit fields and metadata must never contain:

- access, refresh, reset, invitation, or provider tokens;
- authorization headers, cookies, sessions, signatures, API keys, service-role
  keys, encryption keys, passwords, password hashes, or credentials;
- prompts, model input/output, messages, conversation content, attachments, or
  knowledge-file content;
- raw search text or a URL/query string containing search text;
- raw request/response bodies, webhook/provider payloads, stack traces,
  Supabase errors, or exception text;
- payment credentials, checkout URLs, external customer/payment identifiers,
  bank details, or provider references;
- user email, full name, phone number, company name, postal address, IP address,
  device fingerprint, or other unnecessary PII;
- tenant role as a platform authorization assertion;
- secrets encoded, encrypted, hashed, truncated, nested, or renamed to evade
  the policy.

The implementation rejects keys at any nesting depth when their case-folded
name contains `authorization`, `cookie`, `token`, `secret`, `password`,
`credential`, `api_key`, `service_role`, `signature`, `payload`, `prompt`, or
`message`. That prohibited-fragment check supplements, rather than replaces,
the top-level allowlist.

## PII minimization and redaction

- Use internal numeric actor/resource IDs only where required for attribution.
- Keep names, emails, phone numbers, IP addresses, and customer content out of
  the event. Join to restricted identity data during an approved investigation
  instead of copying it into metadata.
- `search_applied` records only whether a search was used.
- Route values are stored as fixed templates, never complete paths containing
  identifiers beyond the separate `resource_id` column.
- Before adding any future metadata field, document purpose, data class,
  retention need, redaction, access, and incident impact.
- Do not log rejected metadata values. Emit only a sanitized validation/audit
  failure code and request correlation ID.

## Shape, encoding, and size

- Metadata must be a JSON object. Arrays/scalars at the root are rejected.
- Keys must be strings and all values must be valid finite JSON values. NaN,
  Infinity, non-serializable types, and malformed JSON are rejected.
- Booleans are rejected anywhere an integer is expected, even though Python
  treats `bool` as a subclass of `int`.
- `limit` must be an integer from 1 through 100. `offset` and `returned_count`
  must be non-negative integers, and `returned_count` must not exceed `limit`.
- `sort_by` is action-specific: `platform_admin.company.list` allows
  `created_at`, `company_name`, `status`, or `id`;
  `platform_admin.company.users.read` allows `created_at`, `email`,
  `full_name`, or `id`; and `platform_admin.company.chatbots.read` allows
  `created_at`, `updated_at`, `bot_name`, or `id`.
- `sort_order` must be `asc` or `desc`.
- `status_filter` is action-specific:
  `platform_admin.company.list` allows `active`, `inactive`, or null;
  `platform_admin.company.subscription_history.read` allows `trialing`,
  `active`, `past_due`, `expired`, `cancelled`, or null.
  Billing-order history uses `status_filter_applied` as a boolean only and
  never records the raw status value.
  `transaction_type_filter` is allowed only on
  `platform_admin.company.ai_credit_transactions.read` and must be
  `included_credit_grant`, `trial_credit_grant`, `usage_debit`,
  `topup_purchase`, `refund`, `manual_adjustment`, `expiry`, `reversal`, or
  null.
  `state_filter` is allowed only on `platform_admin.company.chatbots.read` and
  must be `current`, `archived`, or `all`.
- Period strings, when present, must be non-blank and no longer than 64
  characters.
- Canonicalization uses UTF-8 JSON with sorted keys and compact separators.
- The canonical metadata maximum is **8,192 bytes**. This is a byte limit after
  UTF-8 encoding, not a character estimate.
- Action and resource type must be non-blank and exactly paired by the approved
  action/resource schema.
- Actor ID must be a positive integer; booleans are not integers for this
  purpose.

Malformed, unsupported, prohibited, or oversized metadata must stop event
creation. The service must return a sanitized 503 and must not return already
fetched platform data. Do not truncate, coerce, drop unknown fields, retry
automatically, or fall back to an unaudited response.

## Append-only and access rules

- `anon` and `authenticated` have no table or sequence privileges and no RLS
  policies.
- `service_role` has SELECT/INSERT only on audit events and USAGE on the identity
  sequence. It has no direct UPDATE/DELETE grant or corresponding policy.
- Because `service_role` has BYPASSRLS, application authorization and stronger
  append-only enforcement remain mandatory.
- Migration 026 provides a row-level BEFORE UPDATE OR DELETE rejection trigger.
  It uses SECURITY INVOKER, fixed `search_path=pg_catalog`, and SQLSTATE 55000;
  its function, trigger, privileges, INSERT/SELECT behavior, mutation rejection,
  and rollback cleanup are verified in staging only.
- Direct EXECUTE on the trigger function is revoked from PUBLIC, anon,
  authenticated, and service_role. INSERT and SELECT are unaffected.
- Table owners and superusers are reserved for approved migrations, archive
  maintenance, recovery, or incident response under two-person control.
- Owners and superusers can still alter/disable/drop the trigger; ownership,
  definition, enabled-state, and ACL drift therefore require monitoring.
- No routine application, support, analytics, or reporting workflow may update
  or delete an event.

## Retention and archival policy

### Retention periods

- Keep events queryable in the production database for **13 months** from
  `created_at`.
- Preserve an immutable encrypted archive for **seven years** from
  `created_at`.
- A legal or security hold overrides both deletion schedules until written
  release by the hold authority.
- These periods are production defaults pending formal legal/privacy approval;
  a jurisdictional requirement may lengthen them but must not silently shorten
  them.

### Archive destination and encryption

- The exact production archive URI, region, storage account/project, and owner
  must be filled into the restricted approval record before go-live.
- Use immutable/version-locked object storage with retention lock/WORM controls
  where available; the archive must not share application service credentials.
- Encrypt in transit using the organization-approved TLS baseline and at rest
  with a dedicated production KMS-managed key. Record key ID, owner, rotation
  policy, recovery contacts, and region in the restricted evidence system—not
  this repository.
- Export at least daily in deterministic `created_at,id` order. Include a
  manifest with row count, first/last IDs and timestamps, source project,
  schema/migration hashes, export UTC time, and cryptographic checksums.

### Archive access

- Grant read access only to named security investigation and compliance roles.
- Grant archive write/finalize permission only to the archival service and
  designated security/database operators.
- Separate KMS administration from archive-data administration where possible.
- Require MFA, least privilege, time-bounded elevation, and access logging.
- Review access quarterly and on every personnel or role change.

### Holds and incident preservation

- Legal, privacy, security, or incident commanders may place a documented hold
  identifying scope, authority, start time, custodian, and review date.
- A hold freezes database purge and archive expiration for matching records.
- At incident declaration, preserve relevant database logs, audit exports,
  manifests, release/migration hashes, and access logs before remediation.
- Never alter event content to annotate a hold or incident; store case context
  in the restricted evidence system.

### Deletion authority

- Routine application credentials have no deletion authority.
- Deletion after both the hot-retention threshold and verified archive requires
  written approval from the data owner and security owner; legal/privacy must
  confirm no hold. Two operators must execute and verify the maintenance.
- Migration 026 intentionally provides no maintenance bypass. Retention DELETE
  is blocked until a future separately designed, approved, and staging-tested
  maintenance procedure exists. Do not disable the trigger ad hoc.
- Record deleted ID/time ranges, row counts, archive manifest/checksum, hold
  check, SQL/change reference, operators, approvals, and post-delete checks.
- Never delete mapping rows to enable audit deletion; actor FK preservation is
  intentional.

### Restoration

1. Obtain incident/recovery approval and identify exact archive manifests.
2. Verify object lock state, checksum, signature if used, schema version, row
   count, ID range, and source project.
3. Restore into an isolated access-controlled recovery database or schema, not
   directly over the production audit table.
4. Validate constraints, JSON object shape, actor references or documented
   orphan handling, counts, ordering, and sample checksums.
5. Provide read-only investigator access and record all queries/access.
6. A production merge, if ever required, needs a separate reviewed migration,
   deduplication plan keyed by immutable event ID, backup, and two-person
   approval.
7. Record restoration start/end, operators, approvals, source manifests,
   checksums, target, validation results, and final disposition.

Test an isolated archive restoration quarterly and after archive format, key,
schema, or provider changes.

## Evidence requirements

Retain in the restricted evidence system:

- approved policy version and approvers;
- migration and application commit hashes;
- production project reference and environment;
- daily export manifests/checksums and failures;
- archive/KMS configuration identifiers without secrets;
- access reviews and archive access logs;
- hold placement/release records;
- deletion approvals, row ranges/counts, and post-delete verification;
- quarterly restoration evidence;
- privilege/RLS/trigger drift results;
- audit-failure and reconciliation incident records.

Evidence must not contain live tokens, authorization headers, raw customer
content, or unredacted platform response bodies.

## Policy change control

Any new platform endpoint, action, resource type, metadata field, IP capture,
mutation, export, impersonation, or changed retention period requires a new
threat/privacy review, code and test changes, staging verification, and explicit
policy approval. It must not be enabled by configuration alone.
